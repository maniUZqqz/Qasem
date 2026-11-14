"""Caption quality, round three (review of 2026-11-13): errors a reader sees at once that the earlier rules could not see.

* ASCII digits in Persian copy, a remark to the owner left in the post, «..», claims the brand facts do not make, the glued slogan
  «چغرتر» (the owner's slogan is «با چغر چغر تر شو»), a spoken and a written register mixed in one text, the same opening line used
  by several drafts of one product, and a typing-character NAME printed instead of the character («۳۰ نیم‌فاصله تومان»);
* `repair_caption_copy` fixes the copy that is already stored - once, and never over an edit the owner made.
"""
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.products.models import Product
from apps.stores.models import Store

from . import caption_guard
from .management.commands import repair_caption_copy as repair
from .models import Caption


class _Cap:
    def __init__(self, short="", medium="", long="", cta="", tags=None):
        self.short_text, self.medium_text, self.long_text = short, medium, long
        self.cta, self.hashtags = cta, tags or []


def codes(cap, banned=None, hooks=None):
    return [w["code"] for w in caption_guard.check(cap, banned, hooks)]


class NewRuleTests(SimpleTestCase):
    def test_latin_digits_in_persian_text_are_flagged_but_persian_digits_and_latin_text_are_not(self):
        self.assertIn("latin_digits", codes(_Cap(short="1300 حرکت فارسی")))
        self.assertIn("latin_digits", codes(_Cap(medium="بیش از 1,300 حرکت دارد")))
        self.assertNotIn("latin_digits", codes(_Cap(short="۱٬۳۰۰ حرکت فارسی")))
        self.assertNotIn("latin_digits", codes(_Cap(short="Chagher v2 is here 100")))     # no Persian letter: an English caption
        self.assertNotIn("latin_digits", codes(_Cap(short="نسخهٔ MP4 و PDF")))              # a digit glued to Latin letters is a name

    def test_a_remark_to_the_owner_left_in_the_post_is_flagged(self):
        text = "چغر پیش‌نویس را آماده می‌کند. (مقایسه دربارهٔ روندِ کار است، نه وعدهٔ نتیجه.)"
        self.assertIn("internal_note", codes(_Cap(medium=text)))
        self.assertNotIn("internal_note", codes(_Cap(medium="۵۰ توکن (معادل ۶۰۰٬۰۰۰ تومان) برای یک برنامه")))
        self.assertNotIn("internal_note", codes(_Cap(medium="بسته «عادی» (۵۰ توکن)")))

    def test_doubled_punctuation_is_flagged_an_ellipsis_is_not(self):
        self.assertIn("double_punct", codes(_Cap(long="بدون نیاز به نوشتن دستی است.. 📱")))
        self.assertIn("double_punct", codes(_Cap(long="بخوان،، بنویس")))
        self.assertNotIn("double_punct", codes(_Cap(long="ببینید... و تصمیم بگیرید")))

    def test_claims_the_brand_facts_do_not_make_are_flagged(self):
        for text in ("با یک کلیک برنامه آماده است", "مربی با قلم و تبلت، هرگز نمی‌تواند برنامه را سریع بنویسد", "بهترین دستیار مربی‌ها",
                     "اسکن دستگاه باشگاه هم به صورت خودکار انجام می‌شود"):
            self.assertIn("unverified_claim", codes(_Cap(medium=text)), text)
        # the brand's own wording is fine
        self.assertNotIn("unverified_claim", codes(_Cap(medium="دستگاه‌ها را با دوربین اسکن کنید؛ تا تأییدِ مربی چیزی ثبت نمی‌شود.")))

    def test_the_glued_slogan_is_flagged_the_owners_slogan_is_not(self):
        self.assertIn("slogan_spelling", codes(_Cap(cta="با چغر، چغرتر شو")))
        self.assertIn("slogan_spelling", codes(_Cap(long="با چغر چغر‌تر شو")))                  # half-space inside is the same word
        self.assertNotIn("slogan_spelling", codes(_Cap(cta="با چغر چغر تر شو")))

    def test_a_spoken_and_a_written_register_in_one_text_is_flagged(self):
        self.assertIn("register_mix", codes(_Cap(medium="مربی، وقتت رو صرف مربیگری کن. چغر برنامه را پیش‌نویس می‌کند.")))
        self.assertNotIn("register_mix", codes(_Cap(medium="وقتت رو بذار برای مربیگری؛ چغر برنامه رو می‌نویسه.")))       # all spoken: a voice
        self.assertNotIn("register_mix", codes(_Cap(medium="وقتت را بگذار برای مربیگری؛ چغر برنامه را می‌نویسد.")))      # all written
        self.assertEqual(codes(_Cap(medium="رو می‌کند رو می‌شود")).count("register_mix"), 1)

    def test_a_typing_character_printed_by_name_is_flagged(self):
        self.assertIn("model_artifact", codes(_Cap(long="۲۵ توکن = ۳۰ نیم‌فاصله تومان")))
        self.assertNotIn("model_artifact", codes(_Cap(long="۲۵ توکن = ۳۰۰ هزار تومان")))

    def test_the_same_opening_line_in_several_drafts_is_flagged(self):
        key = caption_guard.hook_key("چرا وقتت رو صرف نوشتن برنامه بذاری؟ 🧠")
        self.assertEqual(key, caption_guard.hook_key("چرا وقتت رو صرف نوشتن برنامه بذاری؟ 🧾"))        # emoji do not make it different
        cap = _Cap(short="چرا وقتت رو صرف نوشتن برنامه بذاری؟ 🧠")
        self.assertIn("repeated_hook", codes(cap, hooks={key: 4}))
        self.assertNotIn("repeated_hook", codes(cap, hooks={key: 1}))
        self.assertNotIn("repeated_hook", codes(cap))                                              # not asked: no cross-caption check


class RepairCommandTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("cap-fix-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="چغر")
        self.product = Product.objects.create(store=self.store, name="سرویس", price=1)

    def make(self, **kw):
        return Caption.objects.create(store=self.store, product=self.product, platform="INSTAGRAM", **kw)

    def test_mechanical_rules_fix_every_caption_of_the_shop(self):
        c = self.make(
            medium_text="چغر پیش‌نویس را آماده می‌کند. (مقایسه دربارهٔ روندِ کار است، نه وعدهٔ نتیجه.)",
            long_text="بیش از 1300 حرکت.. با چغر، چغرتر شو.",
            hashtags=["#برنامهورزشی", "برنامه ورزشی", "چغرتر"],
        )
        call_command("repair_caption_copy", "--store", str(self.store.pk))
        c.refresh_from_db()
        self.assertEqual(c.medium_text, "چغر پیش‌نویس را آماده می‌کند.")
        self.assertEqual(c.long_text, "بیش از ۱۳۰۰ حرکت. با چغر چغر تر شو.")
        self.assertEqual(c.hashtags, ["#برنامه_ورزشی", "برنامه ورزشی", "چغر_تر"])     # only a glued tag is rewritten

    def test_it_is_idempotent_and_check_changes_nothing(self):
        c = self.make(long_text="1300 حرکت", hashtags=["#PDFبرندشده"])
        call_command("repair_caption_copy", "--store", str(self.store.pk), "--check")
        c.refresh_from_db()
        self.assertEqual(c.long_text, "1300 حرکت")
        call_command("repair_caption_copy", "--store", str(self.store.pk))
        c.refresh_from_db()
        stamp = c.updated_at
        call_command("repair_caption_copy", "--store", str(self.store.pk))
        c.refresh_from_db()
        self.assertEqual(c.updated_at, stamp)                                                     # the second run touched nothing
        self.assertEqual((c.long_text, c.hashtags), ("۱۳۰۰ حرکت", ["#PDF_برند_شده"]))

    def test_a_reviewed_text_is_replaced_but_an_edited_one_never_is(self):
        old = "چرا وقتت رو صرف نوشتن برنامه بذاری؟"
        a = self.make(short_text=old)
        b = self.make(short_text="متنی که مالک خودش نوشت")
        table = {a.pk: {"short_text": (repair.sha(old), "وقتِ مربی برای مربیگری است")},
                 b.pk: {"short_text": (repair.sha(old), "وقتِ مربی برای مربیگری است")}}
        original = repair.FIXES
        repair.FIXES = table
        try:
            call_command("repair_caption_copy", "--store", str(self.store.pk))
        finally:
            repair.FIXES = original
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.short_text, "وقتِ مربی برای مربیگری است")
        self.assertEqual(b.short_text, "متنی که مالک خودش نوشت")                                    # the owner's edit wins

    def test_another_store_is_never_touched(self):
        other = Store.objects.create(owner=self.store.owner, name="فروشگاه دیگر")
        c = Caption.objects.create(store=other, product=Product.objects.create(store=other, name="x", price=1), platform="INSTAGRAM", long_text="1300 حرکت")
        call_command("repair_caption_copy", "--store", str(self.store.pk))
        c.refresh_from_db()
        self.assertEqual(c.long_text, "1300 حرکت")

    def test_the_reviewed_replacements_are_well_formed_and_pass_the_guard(self):
        """Every new text of the table must itself be clean: no flag of the quality gate except the price reminder and emoji."""
        self.assertGreaterEqual(len(repair.FIXES), 14)
        for pk, fields in repair.FIXES.items():
            cap = _Cap()
            for field, (fingerprint, new) in fields.items():
                self.assertRegex(fingerprint, r"^[0-9a-f]{12}$")
                self.assertIn(field, repair.FIELDS + ("hashtags",))
                if field == "hashtags":
                    cap.hashtags = new
                else:
                    setattr(cap, {"short_text": "short_text", "medium_text": "medium_text", "long_text": "long_text", "cta": "cta"}[field], new)
            bad = [c for c in codes(cap) if c not in ("price_check", "emoji")]
            self.assertEqual(bad, [], "caption %s: %s" % (pk, bad))

    def test_the_api_warns_about_a_hook_used_by_two_drafts_of_one_product(self):
        a = self.make(short_text="چرا وقتت رو صرف نوشتن برنامه بذاری؟ 🧠")
        self.make(short_text="چرا وقتت رو صرف نوشتن برنامه بذاری؟ 🧾")
        self.make(short_text="یک آغازِ دیگر")
        api = APIClient()
        api.force_authenticate(self.store.owner)
        r = api.get(f"/api/v1/products/{self.product.pk}/captions/")
        self.assertEqual(r.status_code, 200)
        by_id = {row["id"]: {w["code"] for w in row["warnings"]} for row in r.data}
        self.assertIn("repeated_hook", by_id[a.pk])
        self.assertEqual(sum("repeated_hook" in v for v in by_id.values()), 2)


class EmptyHookTests(SimpleTestCase):
    def test_captions_without_an_opening_line_are_not_flagged_as_repeats(self):
        key = caption_guard.hook_key("")
        self.assertEqual(key, "")
        self.assertNotIn("repeated_hook", codes(_Cap(short=""), hooks={"": 5}))


class PersianDigitsInLabelsTests(SimpleTestCase):
    def test_the_voice_pages_say_how_long_ago_with_persian_digits(self):
        from datetime import timedelta

        from django.utils import timezone

        from services.audio import voice_clone

        now = timezone.now()
        self.assertEqual(voice_clone._ago(now - timedelta(hours=19, minutes=5)), "۱۹ ساعت پیش")
        self.assertEqual(voice_clone._ago(now - timedelta(minutes=12)), "۱۲ دقیقه پیش")
        self.assertEqual(voice_clone._ago(now - timedelta(days=3, hours=2)), "۳ روز پیش".replace("۳", "۳"))
        self.assertEqual(voice_clone._ago(None), "هرگز")
