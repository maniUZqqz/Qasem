"""Caption quality, round two: what the first guard missed on store 34.

The first guard caught banned phrases, broken prices, repeated sentences and
emoji noise. Reading the 22 real captions of the flagship product showed four
more defects a tired owner would publish:

* an instruction to the image model printed as copy
  («بدون آدم، فقط فضای باشگاه و تبلت.»),
* hashtags whose words were glued («#برنامهورزشی», «#PDFبرندشده»),
* a long text cut in the middle of a sentence,
* an unconfirmed price repeated in many captions.

And there was no way to rewrite a caption: now there is.
"""
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.products.models import Product
from apps.stores.models import SalesAgentSettings, Store

from . import caption_guard, hashtags
from .models import Caption


class _Cap:
    def __init__(self, short="", medium="", long="", cta="", tags=None):
        self.short_text, self.medium_text, self.long_text = short, medium, long
        self.cta, self.hashtags = cta, tags or []


def codes(cap, banned=None):
    return [w["code"] for w in caption_guard.check(cap, banned)]


class HashtagRepairTests(SimpleTestCase):
    def test_glued_tags_are_split_at_word_boundaries(self):
        self.assertEqual(hashtags.repair("#برنامهورزشی"), "#برنامه_ورزشی")
        self.assertEqual(hashtags.repair("#هوشمصنوعی"), "#هوش_مصنوعی")
        self.assertEqual(hashtags.repair("#PDFبرندشده"), "#PDF_برند_شده")
        self.assertEqual(hashtags.repair("#تکنولوژیورزش"), "#تکنولوژی_ورزش")
        self.assertEqual(hashtags.repair("#چغرورزش"), "#چغر_ورزش")
        self.assertEqual(hashtags.repair("برنامهغذایی"), "برنامه_غذایی")

    def test_good_tags_are_left_alone(self):
        for tag in ["#چغر", "#مربیگری", "#هوش_مصنوعی", "#pdf", "مربی", "هوش مصنوعی", "#ریلز", "#بدنسازی"]:
            self.assertEqual(hashtags.clean(hashtags.repair(tag)), hashtags.clean(tag), tag)

    def test_an_unknown_word_is_never_cut(self):
        self.assertEqual(hashtags.repair("#کارشناسارشد"), "#کارشناسارشد")
        self.assertEqual(hashtags.repair("#برنامهنویسی"), "#برنامهنویسی")

    def test_spaces_become_underscores_like_instagram_wants(self):
        self.assertEqual(hashtags.clean("# هوش  مصنوعی"), "هوش_مصنوعی")
        self.assertEqual(hashtags.repair_all(["چغر", "هوش مصنوعی", "#برنامهورزشی", "", None, 5]),
                         ["چغر", "هوش_مصنوعی", "#برنامه_ورزشی"])

    def test_typed_text_is_parsed_into_tags(self):
        self.assertEqual(hashtags.parse("#چغر #برنامه_ورزشی،#مربی"), ["#چغر", "#برنامه_ورزشی", "#مربی"])
        self.assertEqual(hashtags.parse("چغر، برنامه ورزشی\nمربی"), ["چغر", "برنامه ورزشی", "مربی"])

    def test_a_long_unexplained_tag_is_reported_as_glued(self):
        self.assertTrue(hashtags.is_glued("#مربیگریآنلاینحرفهایایران"))
        self.assertFalse(hashtags.is_glued("#مربیگری"))
        self.assertFalse(hashtags.is_glued("#مربی_بدنسازی_حرفه_ای"))


class GuardRoundTwoTests(SimpleTestCase):
    def test_an_image_instruction_in_the_post_is_flagged(self):
        # caption #33 and #21 of the flagship product
        self.assertIn("image_prompt", codes(_Cap(medium="بازبینی کنید. بدون آدم، فقط فضای باشگاه و تبلت. 📱")))
        self.assertIn("image_prompt", codes(_Cap(medium="بدونِ نیاز به نوشتن دستی، فقط فضای باشگاه و تبلت کافی است.")))
        self.assertNotIn("image_prompt", codes(_Cap(medium="بدون نیاز به نوشتن دستی؛ پیش‌نویس را بازبینی کن.")))

    def test_glued_hashtags_are_flagged_and_good_ones_are_not(self):
        self.assertIn("glued_hashtag", codes(_Cap(tags=["#چغر", "#برنامهورزشی", "#PDFبرندشده"])))
        self.assertNotIn("glued_hashtag", codes(_Cap(tags=["چغر", "برنامه ورزشی", "#مربی_بدنسازی", "pdf"])))

    def test_a_long_text_cut_in_the_middle_is_flagged(self):
        cut = "چغر ابزاری جدید برای مربیان است که به شما کمک می‌کند برنامه ورزشی را سریع‌تر بنویسید. " * 2 + "فقط فضای باشایگاه و تبلت کافی است"
        self.assertIn("truncated", codes(_Cap(long=cut)))
        done = cut + "."
        self.assertNotIn("truncated", codes(_Cap(long=done)))
        self.assertNotIn("truncated", codes(_Cap(long=cut + " 📱")))
        # a short line is not «cut»
        self.assertNotIn("truncated", codes(_Cap(long="لینک در بایو")))

    def test_a_price_in_the_text_asks_for_confirmation(self):
        warned = caption_guard.check(_Cap(medium="هزینه: ۵۰ توکن = ۶۰۰٬۰۰۰ تومان."))
        self.assertEqual([w["code"] for w in warned], ["price_check"])
        self.assertIn("۶۰۰٬۰۰۰ تومان", warned[0]["message"])
        self.assertIn("price_check", codes(_Cap(medium="فقط ۶۰۰ هزار تومان")))
        self.assertNotIn("price_check", codes(_Cap(medium="شروع رایگان است؛ ۵۰ توکن.")))

    def test_a_denied_banned_claim_in_a_caption_is_not_flagged(self):
        banned = ["جایگزین مربی", "تضمین"]
        self.assertNotIn("banned", codes(_Cap(medium="چغر جایگزینِ مربی نیست؛ ما نتیجه را تضمین نمی‌کنیم."), banned))
        self.assertIn("banned", codes(_Cap(medium="نتیجه را تضمین می‌کنیم."), banned))

    def test_the_brands_own_clean_captions_have_no_warnings(self):
        cap = _Cap(
            short="چغر؛ دستیار هوش مصنوعیِ مربی‌ها. پیش‌نویسِ برنامه در کمتر از یک دقیقه؛ تصمیمِ نهایی با خودِ تو.",
            medium="خروجیِ چغر یک PDFِ حرفه‌ای و قابل‌چاپ است؛ نامِ هر حرکت هم لینکِ آموزشِ همان حرکت است.",
            long="خروجی یک PDFِ برندشده و قابل‌چاپ است. شروع رایگان است و کارتِ اعتباری نمی‌خواهد. لینک در بایو.",
            cta="لینک در بایو",
            tags=["#چغر", "#مربی_بدنسازی", "#مربیگری", "#برنامه_تمرینی", "#هوش_مصنوعی", "#باشگاه", "#فیتنس"],
        )
        self.assertEqual(caption_guard.check(cap, ["جایگزین مربی", "تضمین"]), [])


class CaptionEditApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("cap-edit-owner", password="x")
        self.other = User.objects.create_user("cap-edit-other", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغرِ آزمون")
        SalesAgentSettings.objects.create(store=self.store, never_say="تضمین")
        self.product = Product.objects.create(store=self.store, name="سرویس", price=1)
        self.caption = Caption.objects.create(
            store=self.store, product=self.product, platform="INSTAGRAM",
            short_text="یک دقیقه کافی است!",
            medium_text="بدون آدم، فقط فضای باشگاه و تبلت. ۵۰ توکن = ۶۰۰٬۰۰ نتومان",
            hashtags=["#برنامهورزشی", "#هوشمصنوعی", "چغر"],
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.url = f"/api/v1/products/{self.product.pk}/captions/{self.caption.pk}/"

    def test_the_list_shows_glued_hashtags_repaired(self):
        r = self.api.get(f"/api/v1/products/{self.product.pk}/captions/")
        self.assertEqual(r.data[0]["hashtags"], ["#برنامه_ورزشی", "#هوش_مصنوعی", "چغر"])
        self.assertIn("glued_hashtag", {w["code"] for w in r.data[0]["warnings"]})

    def test_rewriting_a_caption_clears_the_warnings(self):
        r = self.api.patch(self.url, {
            "medium_text": "هزینه: ۵۰ توکن = ۶۰۰٬۰۰۰ تومان.",
            "hashtags": "#چغر #برنامه_ورزشی #هوشمصنوعی",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.caption.refresh_from_db()
        self.assertEqual(self.caption.medium_text, "هزینه: ۵۰ توکن = ۶۰۰٬۰۰۰ تومان.")
        # stored repaired and without «#» (the panel adds it)
        self.assertEqual(self.caption.hashtags, ["چغر", "برنامه_ورزشی", "هوش_مصنوعی"])
        got = {w["code"] for w in r.data["warnings"]}
        self.assertNotIn("image_prompt", got)
        self.assertNotIn("broken_number", got)
        self.assertNotIn("glued_hashtag", got)
        # the untouched field stays
        self.assertEqual(self.caption.short_text, "یک دقیقه کافی است!")

    def test_hashtags_can_be_sent_as_a_list(self):
        r = self.api.patch(self.url, {"hashtags": ["چغر", "هوش مصنوعی", "چغر"]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.caption.refresh_from_db()
        self.assertEqual(self.caption.hashtags, ["چغر", "هوش_مصنوعی"])

    def test_bad_requests_get_a_persian_400_and_write_nothing(self):
        for body, code in [
            ({}, "nothing_to_change"),
            ({"short_text": "", "medium_text": "", "long_text": ""}, "empty_caption"),
            ({"medium_text": "ا" * 9000}, "too_long"),
            ({"cta": "ا" * 400}, "cta_too_long"),
        ]:
            r = self.api.patch(self.url, body, format="json")
            self.assertEqual(r.status_code, 400, body)
            self.assertEqual(r.data["error"]["code"], code)
        self.caption.refresh_from_db()
        self.assertEqual(self.caption.short_text, "یک دقیقه کافی است!")

    def test_someone_who_does_not_own_the_product_cannot_edit(self):
        self.api.force_authenticate(self.other)
        r = self.api.patch(self.url, {"short_text": "x"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.caption.refresh_from_db()
        self.assertEqual(self.caption.short_text, "یک دقیقه کافی است!")

    def test_a_caption_of_another_product_is_not_reachable(self):
        other_product = Product.objects.create(store=self.store, name="دیگری", price=1)
        r = self.api.patch(
            f"/api/v1/products/{other_product.pk}/captions/{self.caption.pk}/", {"short_text": "x"}, format="json",
        )
        self.assertEqual(r.status_code, 404)
