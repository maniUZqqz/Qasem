from django.test import SimpleTestCase

from . import fatext


class FaTextTests(SimpleTestCase):
    def test_digits_roundtrip(self):
        self.assertEqual(fatext.en_digits("۹۸٪ و ٣٥"), "98٪ و 35")
        self.assertEqual(fatext.fa_digits("12 از 8"), "۱۲ از ۸")
        self.assertEqual(fatext.fa_digits(None), "")

    def test_normalize_unifies_the_ways_one_claim_can_be_typed(self):
        self.assertEqual(fatext.normalize("۹۸٪ رضایت"), fatext.normalize("98% رضایت"))
        self.assertEqual(fatext.normalize("۹۸ ٪ رضایت"), fatext.normalize("۹۸٪ رضایت"))
        # half-space, kasra, Arabic ي/ك
        self.assertEqual(fatext.normalize("جایگزينِ مربي"), fatext.normalize("جایگزین مربی"))
        self.assertEqual(fatext.normalize("می‌خواهد"), fatext.normalize("میخواهد"))

    def test_contains_phrase(self):
        self.assertTrue(fatext.contains_phrase("رضایتِ ۹۸٪ مربی‌ها", "۹۸٪"))
        self.assertTrue(fatext.contains_phrase("only 98% happy", "۹۸٪"))
        self.assertFalse(fatext.contains_phrase("هدفِ ما جایگزین‌کردنِ مربی نیست", "جایگزین مربی"))
        self.assertFalse(fatext.contains_phrase("anything", ""))


class NegationTests(SimpleTestCase):
    """«جایگزینِ مربی نیست» is the brand's own answer; it must not trip the
    ban on the CLAIM «جایگزین مربی» (the flagship question «جای مربی رو
    می‌گیره؟» got its answer rejected and the chat escalated)."""

    BANNED = ["جایگزین مربی", "تضمین", "درمان", "بدون خطا", "۹۸٪ رضایت"]

    def hits(self, text):
        return [p for p in self.BANNED if fatext.contains_phrase(text, p, ignore_negated=True)]

    def test_the_brands_own_denials_pass(self):
        for text in [
            "نه 🙂 چغر جایگزینِ مربی نیست؛ پیش‌نویس می‌دهد و بازبینی و تصمیمِ نهایی با خودِ مربی است.",
            "نه، چغر جایگزینِ مربی نیست",
            "ما نتیجه را تضمین نمی‌کنیم؛ چغر پیش‌نویس می‌دهد.",
            "ما نتیجه را تضمین نمی کنیم.",
            "چغر درمان نمی‌کند؛ برای این موضوع با پزشک مشورت کن.",
            "چغر نمی‌خواهد جایگزین مربی شود.",
            "هدفِ ما جایگزین مربی شدن نیست.",
            "جایگزین مربی نمی‌شود و نخواهد شد.",
            "هوش مصنوعی ممکن است اشتباه کند و برنامه بدون خطا نیست.",
            "رضایتِ ۹۸٪ نیست",
            "جایگزینِ مربی نیست🙂",
        ]:
            self.assertEqual(self.hits(text), [], text)

    def test_the_claims_themselves_are_still_caught(self):
        for text, phrase in [
            ("چغر جایگزینِ مربی است", "جایگزین مربی"),
            ("چغر جایگزین مربی می‌شود", "جایگزین مربی"),
            ("نه تنها جایگزین مربی است، بلکه ارزان‌تر است", "جایگزین مربی"),
            ("نتیجه را تضمین می‌کنیم", "تضمین"),
            ("تضمین می‌دهیم و پشتیبانی نداریم", "تضمین"),
            ("ما تضمین می‌کنیم؛ نگران نباش", "تضمین"),
            ("این برنامه بدون خطا کار می‌کند", "بدون خطا"),
            ("۹۸٪ رضایت داریم", "۹۸٪ رضایت"),
            ("نتیجه تضمین است. چغر چیزی کم ندارد", "تضمین"),
        ]:
            self.assertIn(phrase, self.hits(text), text)

    def test_one_denied_and_one_made_claim_in_the_same_reply_is_a_violation(self):
        self.assertEqual(
            self.hits("چغر جایگزینِ مربی نیست، ولی نتیجه را تضمین می‌کنیم."), ["تضمین"],
        )

    def test_default_matching_is_unchanged(self):
        # without the flag the plain substring rule stays exactly as before
        self.assertTrue(fatext.contains_phrase("چغر جایگزینِ مربی نیست", "جایگزین مربی"))


class FaDatetimeTests(SimpleTestCase):
    def test_iso_utc_is_shown_in_tehran_shamsi(self):
        # 2026-11-14 02:30 UTC = 06:00 Tehran = 1405/08/23
        self.assertEqual(fatext.fa_datetime("2026-11-14T02:30:00+00:00"), "۱۴۰۵/۰۸/۲۳ ۰۶:۰۰")
        self.assertEqual(fatext.fa_datetime("2026-11-14T02:30:00Z", with_time=False), "۱۴۰۵/۰۸/۲۳")

    def test_late_evening_utc_rolls_to_the_next_tehran_day(self):
        self.assertEqual(fatext.fa_datetime("2026-11-13T21:00:00Z", with_time=False), "۱۴۰۵/۰۸/۲۳")

    def test_unreadable_is_empty(self):
        self.assertEqual(fatext.fa_datetime("not a date"), "")
        self.assertEqual(fatext.fa_datetime(None), "")
